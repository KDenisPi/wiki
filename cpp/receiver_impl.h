/**
 * @file receiver_impl.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-10-15
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_RECEIVER_IMPL_H_
#define WIKI_RECEIVER_IMPL_H_

#include "receiver.h"

namespace wiki {

class ReceiverImpl : public Receiver {
public:

    ReceiverImpl() {
        std::vector<std::string> vals = {"P31"};
        load_dict_list(vals);
    }


    virtual ~ReceiverImpl() {}


    virtual void put_dictionary_value(const dict_key& key, const dict_val& val) override {
        if(!is_dictionary(key))
            return;



    }
};

}
#endif
