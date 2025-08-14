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
#include "rapidjson/document.h"

namespace wiki {

class ItemParser{
public:
    ItemParser() {}
    virtual ~ItemParser() {}

    /**
     * @brief
     *
     * @param buff
     * @return true
     * @return false
     */
    bool create(const char* buff){

        return true;
    }

    /**
     * @brief
     *
     */
    void release(){
        if(ptr_doc){
            ptr_doc.release();
        }
    }

    virtual void process(){}


private:
    std::unique_ptr<rapidjson::Document> ptr_doc;

};

} //namespace
#endif