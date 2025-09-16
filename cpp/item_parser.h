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
    ItemParser(const int index, std::atomic_int* sync) : _index(index), _sync(sync) {
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
    void release(){
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

        auto fn_ready = [&]() {
            return (_sync->load() == 1);
        };

        std::unique_lock<std::mutex> lk(this->cv_m);
        for(;;){
            std::this_thread::sleep_for(std::chrono::milliseconds(10));

            std::cout << "Index: " << this->_index << " Value: " << _sync->load() << std::endl;

            this->cv.wait(lk, fn_ready);

            std::cout << "Data received. Index: " << this->_index << std::endl;

            _sync->store(0);
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            break;
        }

        //std::this_thread::sleep_for(std::chrono::seconds(2));
        std::cout << "Parse finished. Index: " << this->_index << std::endl;
    }

private:
    std::condition_variable cv;
    std::mutex cv_m;

    std::atomic_int* _sync;
    std::shared_ptr<rapidjson::Document> ptr_doc;
    int _index = -1;
};

} //namespace
#endif