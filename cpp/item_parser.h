/**
 * @file item_parser.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-13
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_ITEM_PARSER_H_
#define WIKI_ITEM_PARSER_H_

#include <memory>
#include <atomic>
#include <condition_variable>
#include <thread>
#include <mutex>
#include <chrono>

#include "rapidjson/document.h"

namespace wiki {

class ItemParser{
public:
    ItemParser(const int index, std::atomic_int* sync, const std::shared_ptr<char>& buffer)
        : _index(index), _sync(sync), _buffer(buffer) {
    }

    virtual ~ItemParser() {
        release();
    }

    /**
     * @brief
     *
     * @param buff
     * @return true
     * @return false
     */
    bool load(const char* buff){
        release(); //not sure

        ptr_doc = std::make_shared<rapidjson::Document>();

        ptr_doc->Parse(buff);
        if(ptr_doc->HasParseError()){
            auto err = ptr_doc->GetParseError();
            std::cout << " Parse error: " << std::to_string(err) << " Offset: " << ptr_doc->GetErrorOffset() << std::endl;

            release();
            return false;
        }

        return true;
    }

    /**
     * @brief
     *
     */
    inline void release(){
        if(ptr_doc){
            ptr_doc.reset();
        }
    }

    virtual void process(){}

    /**
     * @brief
     *
     * @return const std::shared_ptr<rapidjson::Document>
     */
    const std::shared_ptr<rapidjson::Document> get() {
        return ptr_doc;
    }

    /**
     * @brief
     *
     */
    void worker(){
        std::cout << "Parse started. Index: " << this->_index << std::endl;

        auto fn_no_data = [&]() {
            return (0 == _sync->load());
        };

        for(;;){
            //std::cout << "Index: " << this->_index << " Value: " << _sync->load() << std::endl;
            while(!is_finish() && fn_no_data());

            if(is_finish()){
                std::cout << "Finish detected. Index: " << this->_index << std::endl;
                break;
            }

            /*
            if(this->_index == 1){
                std::cout << _buffer.get() << "|" << std::endl;
            }
            */

            //std::cout << "Data received. Index: " << this->_index << std::endl;
            auto res = load(_buffer.get());
            if(!res){
                std::cout << "Could not parse data. Index: " << this->_index << std::endl;
                //std::cout << _buffer.get() << "|" << std::endl;
            }
            else{
                auto v_id = ptr_doc->FindMember("id");
                if(v_id != ptr_doc->MemberEnd()){
                    //std::cout << "Index: " << _index << " Item ID: " << v_id->value.GetString() << std::endl;
                }
            }

            _sync->store(0);
            //std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        //std::this_thread::sleep_for(std::chrono::seconds(2));
        std::cout << "Parse finished. Index: " << this->_index << std::endl;
    }

    void set_finish(){
        finish = true;
    }

    inline const bool is_finish(){
        return finish.load();
    }

private:
    std::shared_ptr<char> _buffer;
    std::atomic_int* _sync;
    std::shared_ptr<rapidjson::Document> ptr_doc;
    int _index = -1;

    std::atomic_bool finish = false;

};

} //namespace
#endif